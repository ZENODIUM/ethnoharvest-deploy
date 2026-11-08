#Remove all objects
rm(list=ls(all=TRUE))

#Load needed Packages
library(dplyr)
library(moments)
library(ggplot2)

#Select the data directory where you saved the data files: Example Curves.csv
data_dir <- choose.dir()
phen_curves <-read.table("Example Curves.csv", sep=";",header=T ,fill=TRUE) #sep=";",dec = ".",


#Competitor####
#Selecting one accession which is a strong competitor (i.e. Lysichiton americanus from Frankfurt)
phen_sub<- phen_curves %>% filter(Species_ID == "Lys_ame_Fra")

#Skewness
abs <- phen_sub$Flowering.intensity #Creating a vector with flowering.intensity
times<- phen_sub$Doy #Creating a vector with the DOYs
abs_expand <- rep(times, times=round(abs)) #From relative values to a genuine numerical distribution
skewness<-skewness(abs_expand) #Calculation of the skewness

#Creating the smooth curved
spline<-smooth.spline(phen_sub$Doy,phen_sub$Flowering.intensity, spar=0.4 )
spline_df <- data.frame(Doy = spline$x, Flowering.intensity = spline$y)
spline_df$Flowering.intensity[spline_df$Flowering.intensity < 0.1] <- 0

#Graph
comp<-ggplot() +
  geom_point(data = phen_sub, aes(x = Doy, y = Flowering.intensity), color = "black") +
  geom_line(data = spline_df, aes(x = Doy, y = Flowering.intensity), color = "darkblue", size = 1.4, linetype= "dashed") +
  labs(x = "Day of the year [Doy]", y = "Flowering intensity [%]", title = expression("a) Competitive species: " * italic("Lysichiton americanus") * " (Frankfurt 2022)")) +
  theme_classic()+
  theme(axis.text.y = element_text(size = 14),axis.title.x = element_blank(),axis.title.y = element_text(size = 16),axis.text.x  = element_blank())+
  annotate("text", x = 200, y = 80, label = "Competitiveness = 89%\nStress tolerance = 0%\nFlowering Duration = 49 days\nSkewness = -0.26", 
           size = 5, hjust = 0, color = "black")+
  scale_x_continuous(expand = c(0., 0),breaks=c(0,50,100,150,200,250,300,350),limits=c(-0.5, 365)) +  # Verhindert zusätzlichen Abstand zur Achse
  scale_y_continuous(expand = c(0,0),breaks=c(0,25,50,75,100),limits=c(-0.5, 105))

  

#Stress tolerater####
#Selecting one accession which is a strong competitor (i.e. Hypericum olympicum from Halle)
phen_sub<- phen_curves %>% filter(Species_ID == "Hyp_oly_Hal")


#Creating the smooth curved
spline<-smooth.spline(phen_sub$Doy,phen_sub$Flowering.intensity, spar=0.4 )
spline_df <- data.frame(Doy = spline$x, Flowering.intensity = spline$y)
spline_df$Flowering.intensity[spline_df$Flowering.intensity < 0.1] <- 0

#Graph
stress<-ggplot() +
  geom_point(data = phen_sub, aes(x = Doy, y = Flowering.intensity), color = "black") +
  geom_line(data = spline_df, aes(x = Doy, y = Flowering.intensity), color = "darkblue", size = 1.4, linetype= "dashed") +
  labs(x = "Day of the year [Doy]", y = "Flowering intensity [%]", title = expression("b) Stress tolerating species: " * italic("Hypericum olympicum") * " (Halle 2021)")) +
  theme_classic()+
  theme(axis.text.y = element_blank(),axis.title.x = element_blank(),axis.title.y = element_blank(),axis.text.x  = element_blank())+
  annotate("text", x = 210, y = 80, label = "Competitiveness = 0.5%\nStress tolerance = 80.4%\nFlowering Duration = 167 days", 
           size = 5, hjust = 0, color = "black")+
  scale_x_continuous(expand = c(0., 0),breaks=c(0,50,100,150,200,250,300,350),limits=c(-0.5, 365)) +  # Verhindert zusätzlichen Abstand zur Achse
  scale_y_continuous(expand = c(0,0),breaks=c(0,25,50,75,100),limits=c(-0.5, 105))


#Early flowering####
#Selecting one accession which is a strong competitor (i.e. Anemone nemorosa from Vienna)
phen_sub<- phen_curves %>% filter(Species_ID == "Ane_nem_Vie")

#Skewness
abs <- phen_sub$Flowering.intensity #Creating a vector with flowering.intensity
times<- phen_sub$Doy #Creating a vector with the DOYs
abs_expand <- rep(times, times=round(abs)) #From relative values to a genuine numerical distribution
skewness<-skewness(abs_expand) #Calculation of the skewness

#Creating the smooth curved
spline<-smooth.spline(phen_sub$Doy,phen_sub$Flowering.intensity, spar=0.4 )
spline_df <- data.frame(Doy = spline$x, Flowering.intensity = spline$y)
spline_df$Flowering.intensity[spline_df$Flowering.intensity < 0.1] <- 0

#Graph
early<-ggplot() +
  geom_point(data = phen_sub, aes(x = Doy, y = Flowering.intensity), color = "black") +
  geom_line(data = spline_df, aes(x = Doy, y = Flowering.intensity), color = "darkblue", size = 1.4, linetype= "dashed") +
  labs(x = "Day of the year [Doy]", y = "Flowering intensity [%]", title = expression("c) Early-flowering species: " * italic("Anemone nemorosa") * " (Vienna 2022)")) +
  theme_classic()+
  theme(axis.text.y = element_text(size = 14),axis.title.x = element_text(size = 16),axis.title.y = element_text(size = 16),axis.text.x  = element_text(size = 14))+
  annotate("text", x = 200, y = 80, label = "Flowering Duration = 33 days\nSkewness = 0.41", 
           size = 5, hjust = 0, color = "black")+
  scale_x_continuous(expand = c(0., 0),breaks=c(0,50,100,150,200,250,300,350),limits=c(-0.5, 365)) +  # Verhindert zusätzlichen Abstand zur Achse
  scale_y_continuous(expand = c(0,0),breaks=c(0,25,50,75,100),limits=c(-0.5, 105))



#Late Flowering####
#Selecting one accession which is a strong competitor (i.e. Solidago canadensis from Jena)
phen_sub<- phen_curves %>% filter(Species_ID == "Sol_can_Jen")

#Skewness
abs <- phen_sub$Flowering.intensity #Creating a vector with flowering.intensity
times<- phen_sub$Doy #Creating a vector with the DOYs
abs_expand <- rep(times, times=round(abs)) #From relative values to a genuine numerical distribution
skewness<-skewness(abs_expand) #Calculation of the skewness

#Creating the smooth curved
spline<-smooth.spline(phen_sub$Doy,phen_sub$Flowering.intensity, spar=0.4 )
spline_df <- data.frame(Doy = spline$x, Flowering.intensity = spline$y)
spline_df$Flowering.intensity[spline_df$Flowering.intensity < 0.1] <- 0

#Graph
late<-ggplot() +
  geom_point(data = phen_sub, aes(x = Doy, y = Flowering.intensity), color = "black") +
  geom_line(data = spline_df, aes(x = Doy, y = Flowering.intensity), color = "darkblue", size = 1.4, linetype= "dashed") +
  labs(x = "Day of the year [Doy]", y = "Flowering intensity [%]", title = expression("d) Late-flowering species: " * italic("Solidago canadensis") * " (Jena 2020)")) +
  theme_classic()+
  theme(axis.text.y = element_blank(),axis.title.x = element_text(size = 16),axis.title.y = element_blank(),axis.text.x  = element_text(size = 14))+
  annotate("text", x = 80, y = 80, label = "Flowering Duration = 35 days\nSkewness = -0.25", 
           size = 5, hjust = 0, color = "black")+
  scale_x_continuous(expand = c(0., 0),breaks=c(0,50,100,150,200,250,300,350),limits=c(-0.5, 365)) +  # Verhindert zusätzlichen Abstand zur Achse
  scale_y_continuous(expand = c(0,0),breaks=c(0,25,50,75,100),limits=c(-0.5, 105))


#Plots together####

library(gridExtra)

jpeg("FigureS5_Example Curves.jpeg", width = 4000, height = 2000, res = 300)
grid.arrange(comp, stress, early, late, ncol = 2, nrow = 2)
dev.off()
